from django.shortcuts import render, get_object_or_404, redirect
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.contrib.auth import login, authenticate
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.utils.text import slugify
from django.db.models import Q, Count
from .models import BlogPost, Author, Comment, Reaction, Tag
from .forms import AuthorProfileForm, BlogPostForm
from django.contrib.auth.models import User
from django.http import JsonResponse, Http404, HttpResponseForbidden

def index(request):
    # Get latest posts
    latest_posts = BlogPost.objects.select_related('author__user').prefetch_related('comments').order_by('-created_at')[:6]
    
    # Get featured posts (posts with most comments)
    featured_posts = BlogPost.objects.select_related('author__user').prefetch_related('comments').annotate(
        comment_count=Count('comments')
    ).order_by('-comment_count', '-created_at')[:3]
    
    # Get statistics
    total_posts = BlogPost.objects.count()
    total_authors = Author.objects.count()
    total_comments = Comment.objects.count()
    
    context = {
        'latest_posts': latest_posts,
        'featured_posts': featured_posts,
        'total_posts': total_posts,
        'total_authors': total_authors,
        'total_comments': total_comments,
    }
    return render(request, 'blog/index.html', context)

def blog_post_list(request):
    # Get filter parameters
    sort = request.GET.get('sort', 'latest')

    # Base queryset
    posts = BlogPost.objects.select_related('author__user').prefetch_related('comments', 'reactions')

    # Apply sorting
    if sort == 'popular':
        # Sort by total reactions count
        posts = posts.annotate(
            reaction_count=Count('reactions')
        ).order_by('-reaction_count', '-created_at')
    elif sort == 'commented':
        # Sort by comment count
        posts = posts.annotate(
            comment_count=Count('comments')
        ).order_by('-comment_count', '-created_at')
    else:  # 'latest' is the default
        posts = posts.order_by('-created_at')

    # Get all tags with their post counts
    tags = Tag.objects.annotate(post_count=Count('posts')).order_by('-post_count')[:10]

    # Pagination
    paginator = Paginator(posts, 9)  # Show 9 posts per page
    page = request.GET.get('page')
    posts = paginator.get_page(page)

    context = {
        'posts': posts,
        'sort': sort,
        'tags': tags,
    }
    return render(request, 'blog/blog_post_list.html', context)

def blogger_list(request):
    blogger_list = Author.objects.all().order_by('-created_at')
    paginator = Paginator(blogger_list, 6)  # Show 6 bloggers per page
    
    page = request.GET.get('page')
    try:
        bloggers = paginator.page(page)
    except PageNotAnInteger:
        bloggers = paginator.page(1)
    except EmptyPage:
        bloggers = paginator.page(paginator.num_pages)
    
    return render(request, 'blog/blogger_list.html', {
        'bloggers': bloggers,
        'page_obj': bloggers,
    })

def blog_post_detail(request, slug):
    # Try to get the post by slug first
    try:
        post = BlogPost.objects.get(slug=slug)
    except BlogPost.DoesNotExist:
        # If not found by slug, try to get by ID (in case slug is actually an ID)
        try:
            post = BlogPost.objects.get(id=slug)
            # Redirect to the canonical URL with slug
            return redirect('blog_post_detail', slug=post.slug)
        except (BlogPost.DoesNotExist, ValueError):
            # If neither found or invalid ID, return 404
            raise Http404("Blog post not found")
    
    comments = Comment.objects.filter(post=post).order_by('-created_at')
    
    # Get reaction data
    reaction_choices = Reaction.REACTION_CHOICES
    reaction_counts = {
        reaction_type: post.get_reaction_count(reaction_type)
        for reaction_type, _ in reaction_choices
    }
    user_reaction = post.get_user_reaction(request.user) if request.user.is_authenticated else None
    
    context = {
        'post': post,
        'comments': comments,
        'reaction_choices': reaction_choices,
        'reaction_counts': reaction_counts,
        'user_reaction': user_reaction,
    }
    return render(request, 'blog/blog_post_detail.html', context)

def blogger_detail(request, username):
    try:
        # First check if the user exists
        user = User.objects.get(username=username)
        # Then try to get or create their author profile
        author, created = Author.objects.get_or_create(
            user=user,
            defaults={'bio': f"Welcome to my blog! I'm {user.username}."}
        )
        posts = BlogPost.objects.filter(author=author, status='published').order_by('-created_at')
        return render(request, 'blog/blogger_detail.html', {
            'author': author,
            'posts': posts
        })
    except User.DoesNotExist:
        messages.error(request, f'No user found with username "{username}".')
        return redirect('blogger_list')

def register(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            # Create Author profile for the new user
            Author.objects.create(
                user=user,
                bio=f"Welcome to my blog! I'm {user.username}."
            )
            messages.success(request, 'Registration successful! Please log in.')
            return redirect('login')
    else:
        form = UserCreationForm()
    return render(request, 'blog/register.html', {'form': form})

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            messages.success(request, 'Login successful! Welcome back.')
            return redirect('index')
        else:
            messages.error(request, 'Invalid username or password.')
    return render(request, 'blog/login.html')

@login_required
def edit_profile(request):
    author = get_object_or_404(Author, user=request.user)
    if request.method == 'POST':
        form = AuthorProfileForm(request.POST, instance=author)
        if form.is_valid():
            form.save()
            messages.success(request, 'Your profile has been updated successfully!')
            return redirect('blogger_detail', username=request.user.username)
    else:
        form = AuthorProfileForm(instance=author)
    return render(request, 'blog/edit_profile.html', {'form': form})

@login_required
def create_post(request):
    try:
        author = Author.objects.get(user=request.user)
    except Author.DoesNotExist:
        author = Author.objects.create(
            user=request.user,
            bio=f"Welcome to my blog! I'm {request.user.username}."
        )

    if request.method == 'POST':
        form = BlogPostForm(request.POST, request.FILES)
        if form.is_valid():
            post = form.save(commit=False)
            post.author = author
            
            # Generate a unique slug
            base_slug = slugify(post.title)
            unique_slug = base_slug
            counter = 1
            while BlogPost.objects.filter(slug=unique_slug).exists():
                unique_slug = f"{base_slug}-{counter}"
                counter += 1
            post.slug = unique_slug
            
            post.save()
            messages.success(request, 'Your blog post has been created successfully!')
            return redirect('blog_post_detail', slug=post.slug)
    else:
        form = BlogPostForm()
    
    return render(request, 'blog/create_post.html', {'form': form})

@login_required
def react_to_post(request, slug):
    if request.method == 'POST':
        post = get_object_or_404(BlogPost, slug=slug)
        reaction_type = request.POST.get('reaction_type')
        
        if reaction_type not in dict(Reaction.REACTION_CHOICES):
            return JsonResponse({'error': 'Invalid reaction type'}, status=400)

        # Get or create the reaction
        reaction, created = Reaction.objects.get_or_create(
            post=post,
            user=request.user,
            defaults={'reaction_type': reaction_type}
        )

        # If reaction exists and it's the same type, remove it (toggle off)
        if not created and reaction.reaction_type == reaction_type:
            reaction.delete()
            action = 'removed'
        # If reaction exists but different type, update it
        elif not created:
            reaction.reaction_type = reaction_type
            reaction.save()
            action = 'updated'
        else:
            action = 'added'

        # Get updated reaction counts
        reaction_counts = {
            reaction_type: post.get_reaction_count(reaction_type)
            for reaction_type, _ in Reaction.REACTION_CHOICES
        }

        return JsonResponse({
            'status': 'success',
            'action': action,
            'reaction_counts': reaction_counts
        })

    return JsonResponse({'error': 'Invalid request method'}, status=405)

@login_required
def add_comment(request, slug):
    post = get_object_or_404(BlogPost, slug=slug)
    if request.method == 'POST':
        content = request.POST.get('content')
        if content:
            Comment.objects.create(
                post=post,
                author=request.user,
                content=content
            )
            messages.success(request, 'Your comment has been added successfully!')
        else:
            messages.error(request, 'Comment content cannot be empty.')
    return redirect('blog_post_detail', slug=slug)

@login_required
def delete_comment(request, slug, comment_id):
    comment = get_object_or_404(Comment, id=comment_id, post__slug=slug)
    post = comment.post
    
    # Check if the user is either the comment author or the post author
    if request.user == comment.author or request.user == post.author.user:
        comment.delete()
        messages.success(request, 'Comment deleted successfully.')
    else:
        messages.error(request, 'You do not have permission to delete this comment.')
    
    return redirect('blog_post_detail', slug=slug)

def search_posts(request):
    query = request.GET.get('q', '')
    if query:
        # Split the query into words for more flexible searching
        search_terms = query.split()
        
        # Start with all published posts
        posts = BlogPost.objects.filter(status='published')
        
        # Build a Q object for each search term
        q_objects = Q()
        for term in search_terms:
            q_objects |= (
                Q(title__icontains=term) |
                Q(content__icontains=term) |
                Q(author__user__username__icontains=term)
            )
        
        # Apply the search filter
        posts = posts.filter(q_objects).distinct().order_by('-created_at')
    else:
        posts = BlogPost.objects.none()
    
    # Pagination
    paginator = Paginator(posts, 9)  # Show 9 posts per page
    page = request.GET.get('page')
    
    try:
        posts = paginator.page(page)
    except PageNotAnInteger:
        posts = paginator.page(1)
    except EmptyPage:
        posts = paginator.page(paginator.num_pages)
    
    return render(request, 'blog/search_results.html', {
        'query': query,
        'posts': posts,
        'page_obj': posts,
        'total_results': posts.paginator.count if query else 0,
    })

@login_required
def edit_post(request, slug):
    post = get_object_or_404(BlogPost, slug=slug)
    
    # Check if the user is the author
    if request.user != post.author.user:
        return HttpResponseForbidden("You don't have permission to edit this post.")
    
    if request.method == 'POST':
        form = BlogPostForm(request.POST, request.FILES, instance=post)
        if form.is_valid():
            post = form.save(commit=False)
            post.save()
            messages.success(request, 'Post updated successfully!')
            return redirect('blog_post_detail', slug=post.slug)
    else:
        form = BlogPostForm(instance=post)
    
    return render(request, 'blog/edit_post.html', {
        'form': form,
        'post': post
    })

@login_required
def delete_post(request, slug):
    post = get_object_or_404(BlogPost, slug=slug)
    
    # Check if the user is the author
    if request.user != post.author.user:
        return HttpResponseForbidden("You don't have permission to delete this post.")
    
    if request.method == 'POST':
        post.delete()
        messages.success(request, 'Post deleted successfully!')
        return redirect('blog_post_list')
    
    return redirect('blog_post_detail', slug=slug)
